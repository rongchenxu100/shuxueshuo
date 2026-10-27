"""Durable search quotas and single-host admission, independent of private files."""

import os
from contextlib import nullcontext
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from ..product.db import transaction
from ..product.models import metadata
from .storage import SearchError

CONTROL = metadata.tables['search_admission_control']
TICKETS = metadata.tables['search_admission_tickets']
ACTIVE = ('reserved', 'running')
PAID = ('generation', 'rerun')
QUOTA_TIMEZONE = ZoneInfo('Asia/Shanghai')
_DAILY_LIMIT_FIELDS = frozenset({
    'generation_account_daily', 'rerun_account_daily',
    'generation_global_daily', 'rerun_global_daily',
})


@dataclass(frozen=True)
class SearchLimits:
    # None disables that daily quota check (local development only).
    generation_account_daily: int | None = 10
    rerun_account_daily: int | None = 3
    generation_global_daily: int | None = 100
    rerun_global_daily: int | None = 50
    generation_account_concurrency: int = 1
    generation_workers: int = 2
    generation_queue_size: int = 4
    upload_account_limit: int = 2
    upload_global_limit: int = 10

    def __post_init__(self):
        positive = {'generation_account_concurrency', 'generation_workers', 'upload_account_limit', 'upload_global_limit'}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in _DAILY_LIMIT_FIELDS:
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError('Invalid SEARCH_' + field.name.upper())
                continue
            if type(value) is not int or value < (1 if field.name in positive else 0):
                raise ValueError('Invalid SEARCH_' + field.name.upper())

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        values = {}
        for field in fields(cls):
            name = 'SEARCH_' + field.name.upper()
            if name in environ:
                try:
                    values[field.name] = int(environ[name])
                except (TypeError, ValueError) as exc:
                    raise ValueError('Invalid ' + name) from exc
        return cls(**values)

    @classmethod
    def local_development(cls):
        """Loopback-only site: no daily LLM search generation/rerun quotas."""
        return cls(
            generation_account_daily=None,
            rerun_account_daily=None,
            generation_global_daily=None,
            rerun_global_daily=None,
        )


@dataclass(frozen=True)
class AdmissionTicket:
    id: str
    search_id: str
    kind: str
    state: str
    created: bool = False


def _ticket(row, *, created=False):
    return AdmissionTicket(str(row['id']), row['search_id'], row['kind'], row['state'], created)


def _user_id(user):
    return UUID(str(user['id'] if isinstance(user, dict) else user))


class SearchAdmission:
    def __init__(self, db, *, config=None, clock=None):
        self.db = db
        self.config = config or SearchLimits.from_env()
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError('Search admission requires an aware clock')
        return value.astimezone(UTC)

    def _connection(self, connection):
        return nullcontext(connection) if connection is not None else transaction(self.db)

    def _control(self, connection):
        return connection.execute(sa.select(CONTROL).where(CONTROL.c.singleton.is_(True)).with_for_update()).mappings().one()

    def get_ticket(self, ticket_id):
        with transaction(self.db) as connection:
            row = connection.execute(sa.select(TICKETS).where(TICKETS.c.id == UUID(str(ticket_id)))).mappings().first()
            return _ticket(row) if row else None

    def find_request(self, user, kind, request_id):
        if request_id is None:
            return None
        with transaction(self.db) as connection:
            row = connection.execute(sa.select(TICKETS).where(
                TICKETS.c.user_id == _user_id(user), TICKETS.c.kind == kind,
                TICKETS.c.request_id == request_id)).mappings().first()
            return _ticket(row) if row else None

    def ticket_states(self, ticket_ids):
        if not ticket_ids:
            return {}
        identifiers = [UUID(str(value)) for value in ticket_ids]
        with transaction(self.db) as connection:
            return {str(row.id): row.state for row in connection.execute(sa.select(TICKETS.c.id, TICKETS.c.state).where(TICKETS.c.id.in_(identifiers)))}

    def reserve(self, user, kind, search_id, request_id=None, connection=None):
        if kind not in (*PAID, 'continuation'):
            raise ValueError('Unknown search admission kind')
        if not isinstance(search_id, str) or not search_id or len(search_id) > 128:
            raise ValueError('Invalid search id')
        if request_id is not None and (not isinstance(request_id, str) or not request_id or len(request_id) > 200):
            raise SearchError('search.request_id', 400)
        owner = _user_id(user)
        with self._connection(connection) as current:
            control = self._control(current)
            if request_id is not None:
                existing = current.execute(sa.select(TICKETS).where(
                    TICKETS.c.user_id == owner, TICKETS.c.kind == kind, TICKETS.c.request_id == request_id)).mappings().first()
                if existing:
                    if existing['search_id'] != search_id:
                        raise SearchError('search.request_conflict', 409)
                    return _ticket(existing)
            now = self._now()
            quota_day = now.astimezone(QUOTA_TIMEZONE).date()
            if kind in PAID and not control['generation_enabled']:
                raise SearchError('search.generation_paused', 503)
            active = current.execute(sa.select(
                sa.func.count().label('total'),
                sa.func.count().filter(TICKETS.c.user_id == owner).label('account'),
            ).where(TICKETS.c.state.in_(ACTIVE))).mappings().one()
            if active['account'] >= self.config.generation_account_concurrency:
                raise SearchError('search.account_busy', 429)
            if active['total'] >= self.config.generation_workers + self.config.generation_queue_size:
                raise SearchError('search.queue_full', 429)
            if kind in PAID:
                usage = current.execute(sa.select(
                    sa.func.count().label('total'),
                    sa.func.count().filter(TICKETS.c.user_id == owner).label('account'),
                ).where(TICKETS.c.quota_day == quota_day, TICKETS.c.kind == kind,
                        sa.or_(TICKETS.c.consumed.is_(True), TICKETS.c.state == 'reserved'))).mappings().one()
                account_limit = getattr(self.config, kind + '_account_daily')
                global_limit = getattr(self.config, kind + '_global_daily')
                if account_limit is not None and usage['account'] >= account_limit:
                    raise SearchError('search.daily_' + kind + '_limit', 429)
                if global_limit is not None and usage['total'] >= global_limit:
                    raise SearchError('search.global_' + kind + '_limit', 429)
            row = current.execute(TICKETS.insert().values(
                id=uuid4(), user_id=owner, search_id=search_id, kind=kind, request_id=request_id,
                quota_day=quota_day, accepted_at=now, state='reserved', consumed=False,
            ).returning(TICKETS)).mappings().one()
            return _ticket(row, created=True)

    def start(self, ticket_id, *, connection=None):
        with self._connection(connection) as current:
            control = self._control(current)
            now = self._now()
            row = current.execute(sa.select(TICKETS).where(TICKETS.c.id == UUID(str(ticket_id)))).mappings().first()
            if row is None or row['state'] != 'reserved':
                return False
            if row['kind'] in PAID and not control['generation_enabled']:
                current.execute(TICKETS.update().where(TICKETS.c.id == row['id']).values(
                    state='cancelled', finished_at=now, error_code='search.generation_paused'))
                return False
            running = current.scalar(sa.select(sa.func.count()).where(TICKETS.c.state == 'running'))
            if running >= self.config.generation_workers:
                raise SearchError('search.queue_full', 429)
            current.execute(TICKETS.update().where(TICKETS.c.id == row['id']).values(
                state='running', started_at=now, consumed=row['kind'] in PAID))
            return True

    def finish(self, ticket_id, *, error_code=None):
        with transaction(self.db) as connection:
            self._control(connection)
            return connection.execute(TICKETS.update().where(
                TICKETS.c.id == UUID(str(ticket_id)), TICKETS.c.state == 'running').values(
                    state='finished', finished_at=self._now(), error_code=error_code)).rowcount > 0

    def cancel(self, ticket_id, *, error_code=None, connection=None):
        with self._connection(connection) as current:
            self._control(current)
            return current.execute(TICKETS.update().where(
                TICKETS.c.id == UUID(str(ticket_id)), TICKETS.c.state == 'reserved').values(
                    state='cancelled', finished_at=self._now(), error_code=error_code)).rowcount > 0

    def cancel_for_submissions(self, search_ids, *, connection=None, error_code='search.not_found'):
        if not search_ids:
            return []
        with self._connection(connection) as current:
            self._control(current)
            return [str(value) for value in current.scalars(TICKETS.update().where(
                TICKETS.c.search_id.in_(search_ids), TICKETS.c.state == 'reserved').values(
                    state='cancelled', finished_at=self._now(), error_code=error_code).returning(TICKETS.c.id))]

    def recover(self):
        with transaction(self.db) as connection:
            self._control(connection)
            now = self._now()
            reserved = connection.execute(TICKETS.update().where(TICKETS.c.state == 'reserved').values(
                state='cancelled', finished_at=now, error_code='search.interrupted')).rowcount
            running = connection.execute(TICKETS.update().where(TICKETS.c.state == 'running').values(
                state='interrupted', finished_at=now, error_code='search.interrupted')).rowcount
            return {'cancelled': reserved, 'interrupted': running}

    def generation_enabled(self):
        with transaction(self.db) as connection:
            return connection.scalar(sa.select(CONTROL.c.generation_enabled).where(CONTROL.c.singleton.is_(True))) is True

    def require_generation_enabled(self):
        if not self.generation_enabled():
            raise SearchError('search.generation_paused', 503)

    def set_generation_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Generation state must be boolean')
        with transaction(self.db) as connection:
            self._control(connection)
            now = self._now()
            connection.execute(CONTROL.update().where(CONTROL.c.singleton.is_(True)).values(
                generation_enabled=enabled, updated_at=now))
            if enabled:
                return []
            return [str(value) for value in connection.scalars(TICKETS.update().where(
                TICKETS.c.kind.in_(PAID), TICKETS.c.state == 'reserved').values(
                    state='cancelled', finished_at=now, error_code='search.generation_paused').returning(TICKETS.c.id))]
