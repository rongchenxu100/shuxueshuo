from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.search.admission import (
    CONTROL,
    TICKETS,
    SearchAdmission,
    SearchLimits,
)
from shuxueshuo_server.search.storage import SearchError
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import student, submission


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def admission(repository):
    value = SearchAdmission(repository.db, clock=repository.clock)
    value.set_generation_enabled(True)
    return value


def ticket_row(admission, ticket):
    with admission.db.connect() as connection:
        return connection.execute(sa.select(TICKETS).where(TICKETS.c.id == UUID(ticket.id))).mappings().one()


def complete(admission, user, kind='generation', search_id='fixture'):
    ticket = admission.reserve(user, kind, search_id)
    assert admission.start(ticket.id)
    assert admission.finish(ticket.id)
    return ticket


def test_defaults_and_env_are_validated():
    assert SearchLimits.from_env({}) == SearchLimits(10, 3, 100, 50, 1, 2, 4, 2, 10)
    values = {'SEARCH_GENERATION_ACCOUNT_DAILY': '11', 'SEARCH_RERUN_GLOBAL_DAILY': '60',
              'SEARCH_GENERATION_QUEUE_SIZE': '0', 'SEARCH_UPLOAD_GLOBAL_LIMIT': '12'}
    configured = SearchLimits.from_env(values)
    assert (configured.generation_account_daily, configured.rerun_global_daily,
            configured.generation_queue_size, configured.upload_global_limit) == (11, 60, 0, 12)
    for name, value in (('SEARCH_UPLOAD_GLOBAL_LIMIT', '0'), ('SEARCH_GENERATION_WORKERS', '-1'),
                        ('SEARCH_GENERATION_ACCOUNT_DAILY', '-1'), ('SEARCH_GENERATION_QUEUE_SIZE', '1.5')):
        with pytest.raises(ValueError, match=name):
            SearchLimits.from_env({name: value})
    unlimited = SearchLimits.local_development()
    assert unlimited.generation_account_daily is unlimited.rerun_account_daily is None
    assert unlimited.generation_global_daily is unlimited.rerun_global_daily is None


def test_local_development_daily_quotas_are_unlimited(repository):
    admission = SearchAdmission(repository.db, config=SearchLimits.local_development(), clock=repository.clock)
    admission.set_generation_enabled(True)
    owner = student(repository)
    for index in range(SearchLimits().generation_account_daily + 1):
        complete(admission, owner, 'generation', search_id=f'generation-{index}')
    for index in range(SearchLimits().rerun_account_daily + 1):
        complete(admission, owner, 'rerun', search_id=f'rerun-{index}')


def test_closed_by_default_and_continuation_does_not_need_daily_quota(repository):
    admission = SearchAdmission(repository.db, config=SearchLimits(generation_account_daily=0, rerun_account_daily=0))
    owner = student(repository)
    assert not admission.generation_enabled()
    for kind in ('generation', 'rerun'):
        with pytest.raises(SearchError, match='search.generation_paused'):
            admission.reserve(owner, kind, 'fixture')
    ticket = complete(admission, owner, 'continuation')
    assert ticket_row(admission, ticket)['consumed'] is False


@pytest.mark.parametrize(('kind', 'limit'), [('generation', 10), ('rerun', 3)])
def test_account_daily_quotas_count_started_failures_and_are_separate(repository, admission, kind, limit):
    owner = student(repository)
    for _index in range(limit):
        ticket = admission.reserve(owner, kind, 'fixture')
        assert admission.start(ticket.id)
        admission.finish(ticket.id, error_code='fixture.failure')
    with pytest.raises(SearchError, match='search.daily_' + kind + '_limit') as rejected:
        admission.reserve(owner, kind, 'next')
    assert rejected.value.status == 429
    other_kind = 'generation' if kind == 'rerun' else 'rerun'
    complete(admission, owner, other_kind)
    complete(admission, student(repository), kind)


@pytest.mark.parametrize('kind', ['generation', 'rerun'])
def test_global_daily_quota_includes_other_accounts_and_reservations(repository, kind):
    admission = SearchAdmission(repository.db, config=SearchLimits(generation_global_daily=2, rerun_global_daily=2))
    admission.set_generation_enabled(True)
    owners = [student(repository) for _index in range(3)]
    complete(admission, owners[0], kind)
    pending = admission.reserve(owners[1], kind, 'pending')
    with pytest.raises(SearchError, match='search.global_' + kind + '_limit'):
        admission.reserve(owners[2], kind, 'rejected')
    assert admission.cancel(pending.id)
    complete(admission, owners[2], kind)


def test_account_concurrency_spans_kind_and_is_global_between_instances(repository, admission):
    owner = student(repository)
    ticket = admission.reserve(owner, 'generation', 'fixture')
    other = SearchAdmission(repository.db, clock=repository.clock)
    for kind in ('generation', 'rerun', 'continuation'):
        with pytest.raises(SearchError, match='search.account_busy'):
            other.reserve(owner, kind, 'other')
    admission.start(ticket.id)
    with pytest.raises(SearchError, match='search.account_busy'):
        other.reserve(owner, 'continuation', 'other')
    admission.finish(ticket.id)
    assert other.reserve(owner, 'continuation', 'other').created


def test_concurrent_account_reservations_have_exactly_one_winner(repository, admission):
    owner = student(repository)
    barrier = Barrier(8)

    def reserve(index):
        barrier.wait()
        try:
            return admission.reserve(owner, 'generation', str(index)).id
        except SearchError as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert results.count('search.account_busy') == 7


def test_concurrent_global_admission_has_two_running_four_waiting(repository, admission):
    owners = [student(repository) for _index in range(10)]
    barrier = Barrier(10)

    def reserve(owner):
        barrier.wait()
        try:
            return admission.reserve(owner, 'generation', 'fixture')
        except SearchError as exc:
            return exc.code

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(reserve, owners))
    assert results.count('search.queue_full') == 4
    tickets = [result for result in results if not isinstance(result, str)]
    assert admission.start(tickets[0].id)
    assert admission.start(tickets[1].id)
    with pytest.raises(SearchError, match='search.queue_full'):
        admission.start(tickets[2].id)
    assert admission.get_ticket(tickets[2].id).state == 'reserved'
    assert admission.finish(tickets[0].id)
    assert admission.start(tickets[2].id)


def test_concurrent_daily_limit_is_atomic_even_with_account_parallelism(repository):
    admission = SearchAdmission(repository.db, config=SearchLimits(generation_account_daily=2,
        generation_global_daily=2, generation_account_concurrency=10, generation_queue_size=10))
    admission.set_generation_enabled(True)
    owners = [student(repository) for _index in range(8)]
    barrier = Barrier(8)

    def reserve(owner):
        barrier.wait()
        try:
            return admission.reserve(owner, 'generation', 'fixture')
        except SearchError as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(reserve, owners))
    assert results.count('search.global_generation_limit') == 6


def test_concurrent_request_retry_is_idempotent_and_survives_stop(repository, admission):
    owner = student(repository)
    barrier = Barrier(6)

    def reserve(_index):
        barrier.wait()
        return admission.reserve(owner, 'rerun', 'fixture', request_id='same-request')

    with ThreadPoolExecutor(6) as pool:
        tickets = list(pool.map(reserve, range(6)))
    assert len({ticket.id for ticket in tickets}) == 1
    assert sum(ticket.created for ticket in tickets) == 1
    admission.set_generation_enabled(False)
    retry = admission.reserve(owner, 'rerun', 'fixture', request_id='same-request')
    assert retry.id == tickets[0].id and not retry.created and retry.state == 'cancelled'
    with pytest.raises(SearchError, match='search.request_conflict'):
        admission.reserve(owner, 'rerun', 'different', request_id='same-request')


def test_request_id_scope_does_not_cross_accounts_or_kinds(repository, admission):
    first, second = student(repository), student(repository)
    original = admission.reserve(first, 'generation', 'first', request_id='same')
    other = admission.reserve(second, 'generation', 'second', request_id='same')
    assert original.id != other.id
    assert admission.find_request(first, 'generation', 'same').id == original.id
    assert admission.find_request(second, 'generation', 'same').id == other.id
    assert admission.find_request(first, 'rerun', 'same') is None
    assert admission.find_request(first, 'generation', 'absent') is None


def test_concurrent_stop_and_start_never_refunds_a_started_ticket(repository, admission):
    owner = student(repository)
    ticket = admission.reserve(owner, 'generation', 'fixture')
    barrier = Barrier(2)

    def start():
        barrier.wait()
        return admission.start(ticket.id)

    def stop():
        barrier.wait()
        return admission.set_generation_enabled(False)

    with ThreadPoolExecutor(2) as pool:
        started = pool.submit(start)
        stopped = pool.submit(stop)
        did_start, cancelled = started.result(), stopped.result()
    row = ticket_row(admission, ticket)
    assert row['consumed'] is did_start
    assert row['state'] == ('running' if did_start else 'cancelled')
    assert cancelled == ([] if did_start else [ticket.id])


def test_rolled_back_start_does_not_charge_or_leave_running_ticket(repository, admission):
    owner = student(repository)
    ticket = admission.reserve(owner, 'generation', 'fixture')
    with pytest.raises(RuntimeError, match='rollback'), repository.db.begin() as connection:
        assert admission.start(ticket.id, connection=connection)
        raise RuntimeError('rollback')
    row = ticket_row(admission, ticket)
    assert row['state'] == 'reserved' and not row['consumed'] and row['started_at'] is None
    assert admission.start(ticket.id)


def test_ticket_and_submission_transaction_rollback_releases_all_reservation(repository, admission):
    owner = student(repository)
    with pytest.raises(RuntimeError, match='rollback'), repository.db.begin() as connection:
        ticket = admission.reserve(owner, 'generation', 'fixture', connection=connection)
        raise RuntimeError('rollback')
    assert admission.get_ticket(ticket.id) is None
    complete(admission, owner)


def test_start_is_atomic_idempotent_and_failed_enqueue_does_not_consume(repository, admission):
    owner = student(repository)
    ticket = admission.reserve(owner, 'generation', 'fixture')
    assert admission.cancel(ticket.id, error_code='fixture.enqueue_failed')
    assert not admission.start(ticket.id)
    assert not ticket_row(admission, ticket)['consumed']
    started = admission.reserve(owner, 'generation', 'fixture')
    assert admission.start(started.id)
    assert not admission.start(started.id)
    assert not admission.cancel(started.id)
    assert ticket_row(admission, started)['consumed']
    assert admission.finish(started.id)
    assert not admission.finish(started.id)


def test_midnight_uses_acceptance_day_in_shanghai_even_when_start_is_later(repository, admission):
    owner = student(repository)
    repository.test_time[0] = datetime(2026, 10, 25, 15, 59, 59, tzinfo=UTC)
    pending = admission.reserve(owner, 'generation', 'before-midnight')
    repository.test_time[0] += timedelta(seconds=2)
    assert admission.start(pending.id)
    admission.finish(pending.id)
    assert str(ticket_row(admission, pending)['quota_day']) == '2026-10-25'
    today = complete(admission, owner)
    assert str(ticket_row(admission, today)['quota_day']) == '2026-10-26'


def test_recovery_releases_reservations_preserves_used_quota_and_does_not_reset_day(repository):
    admission = SearchAdmission(repository.db, config=SearchLimits(generation_account_daily=1), clock=repository.clock)
    admission.set_generation_enabled(True)
    first, second = student(repository), student(repository)
    started = admission.reserve(first, 'generation', 'started')
    pending = admission.reserve(second, 'generation', 'pending')
    admission.start(started.id)
    restarted = SearchAdmission(repository.db, config=admission.config, clock=repository.clock)
    assert restarted.recover() == {'cancelled': 1, 'interrupted': 1}
    assert restarted.recover() == {'cancelled': 0, 'interrupted': 0}
    assert restarted.ticket_states([started.id, pending.id]) == {started.id: 'interrupted', pending.id: 'cancelled'}
    with pytest.raises(SearchError, match='search.daily_generation_limit'):
        restarted.reserve(first, 'generation', 'again')
    complete(restarted, second)
    repository.test_time[0] += timedelta(days=1)
    complete(restarted, first)


def test_deletion_retains_used_quota_and_only_cancels_reserved(repository, admission):
    first, second = student(repository), student(repository)
    started_submission, _created = submission(repository, first)
    pending_submission, _created = submission(repository, second)
    started = admission.reserve(first, 'generation', started_submission['id'])
    pending = admission.reserve(second, 'generation', pending_submission['id'])
    admission.start(started.id)
    removed = admission.cancel_for_submissions([started_submission['id'], pending_submission['id']])
    assert removed == [pending.id]
    with repository.db.begin() as connection:
        connection.execute(sa.delete(sa.table('search_submissions', sa.column('id'))).where(
            sa.column('id').in_([started_submission['id'], pending_submission['id']])))
    assert ticket_row(admission, started)['consumed']
    assert admission.get_ticket(started.id).state == 'running'
    assert not ticket_row(admission, pending)['consumed']
    with pytest.raises(SearchError, match='search.account_busy'):
        admission.reserve(first, 'generation', 'still-executing')
    admission.finish(started.id)
    assert admission.reserve(first, 'generation', 'new').created


def test_stop_is_hot_cross_instance_preserves_running_and_allows_local_continuation(repository, admission):
    owners = [student(repository) for _index in range(4)]
    running = admission.reserve(owners[0], 'generation', 'running')
    admission.start(running.id)
    generation = admission.reserve(owners[1], 'generation', 'queued')
    rerun = admission.reserve(owners[2], 'rerun', 'queued-rerun')
    continuation = admission.reserve(owners[3], 'continuation', 'continuation')
    operator = SearchAdmission(repository.db, clock=repository.clock)
    assert set(operator.set_generation_enabled(False)) == {generation.id, rerun.id}
    with pytest.raises(SearchError, match='search.generation_paused'):
        admission.require_generation_enabled()
    assert not admission.start(generation.id)
    assert admission.start(continuation.id)
    assert admission.get_ticket(running.id).state == 'running'
    operator.set_generation_enabled(True)
    admission.require_generation_enabled()
    assert not admission.start(generation.id)


@pytest.mark.parametrize('column', ['user_id', 'search_id', 'kind', 'request_id', 'quota_day', 'accepted_at'])
def test_app_cannot_reassign_ledger_identity_or_delete_quota(repository, admission, column):
    ticket = complete(admission, student(repository))
    with pytest.raises(DBAPIError), repository.db.begin() as connection:
        connection.execute(TICKETS.update().where(TICKETS.c.id == UUID(ticket.id)).values({column: TICKETS.c[column]}))
    with pytest.raises(DBAPIError), repository.db.begin() as connection:
        connection.execute(TICKETS.delete())
    with pytest.raises(DBAPIError), repository.db.begin() as connection:
        connection.execute(CONTROL.delete())
