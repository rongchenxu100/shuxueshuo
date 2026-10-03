"""Real PostgreSQL transactions using the restricted application role."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.tutor_demo.limits import (
    BudgetUnavailable,
    CallBudget,
    DialogueLimited,
)

ALICE = '00000000-0000-0000-0000-000000000001'
BOB = '00000000-0000-0000-0000-000000000002'


def test_personal_budget_is_shared_across_sessions_and_restarts(budget_db):
    now = [datetime(2026, 10, 3, 23, 59, 59, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()]
    remaining = [CallBudget(budget_db, user_daily_limit=2, clock=lambda: now[0]).reserve(str(i), user_id=ALICE) for i in range(2)]
    assert remaining == [1, 0]
    budget = CallBudget(budget_db, user_daily_limit=2, clock=lambda: now[0])
    with pytest.raises(DialogueLimited) as error:
        budget.reserve('third-lesson', user_id=ALICE)
    assert error.value.code == 'user_daily_limit'
    assert error.value.retry_after == 2
    budget_db.dispose()  # Reconnect: no process-local accounting state.
    budget.reserve('bobs-lesson', user_id=BOB)
    with budget_db.connect() as c:
        assert c.scalar(text('SELECT calls FROM tutor_daily_usage')) == 3
        assert c.scalar(text("SELECT count(*) FROM tutor_session_usage WHERE session_id='third-lesson'")) == 0
    now[0] += 2
    budget.reserve('third-lesson', user_id=ALICE)
    with budget_db.connect() as c:
        assert c.execute(text('SELECT calls FROM tutor_user_daily_usage WHERE user_id=:user ORDER BY day'), {'user': ALICE}).fetchall() == [(2,), (1,)]


def test_account_and_global_limits_are_atomic_under_concurrency(budget_db):
    def reserve(i):
        try:
            CallBudget(budget_db, user_daily_limit=3, daily_limit=5).reserve(str(i), user_id=ALICE if i < 12 else BOB)
            return True
        except DialogueLimited:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(24))) == 5
    with budget_db.connect() as c:
        assert c.execute(text('SELECT SUM(calls), MAX(calls) FROM tutor_user_daily_usage')).one() == (5, 3)
        assert c.scalar(text('SELECT calls FROM tutor_daily_usage')) == 5
        assert c.scalar(text('SELECT SUM(calls) FROM tutor_session_usage')) == 5


def test_global_rejection_rolls_back_new_account_and_session_rows(budget_db):
    budget = CallBudget(budget_db, daily_limit=1)
    budget.reserve('old', user_id=ALICE)
    with pytest.raises(DialogueLimited) as error:
        budget.reserve('new', user_id=BOB)
    assert error.value.code == 'daily_limit'
    with budget_db.connect() as c:
        assert c.execute(text('SELECT session_id,calls FROM tutor_session_usage')).fetchall() == [('old', 1)]
        assert c.scalar(text('SELECT COUNT(*) FROM tutor_user_daily_usage')) == 1
        assert c.scalar(text('SELECT calls FROM tutor_daily_usage')) == 1


def test_invalid_owner_and_explicit_zero_fail_closed(budget_db):
    budget = CallBudget(budget_db, user_daily_limit=0)
    with pytest.raises(BudgetUnavailable):
        budget.reserve('new', user_id='')
    with pytest.raises(DialogueLimited) as error:
        budget.reserve('new', user_id=ALICE)
    assert error.value.code == 'user_daily_limit'
    with budget_db.connect() as c:
        assert c.scalar(text('SELECT COUNT(*) FROM tutor_daily_usage')) == 0


def test_failed_call_is_charged_and_cooldown_persists(budget_db):
    budget = CallBudget(budget_db, user_daily_limit=2, failure_cooldown=5, clock=lambda: 1000)
    budget.reserve('first', user_id=ALICE)
    budget.failed('first')
    restarted = CallBudget(budget_db, user_daily_limit=2, clock=lambda: 1001)
    with pytest.raises(DialogueLimited) as error:
        restarted.reserve('first', user_id=ALICE)
    assert error.value.code == 'retry_cooldown'
    restarted.reserve('new', user_id=ALICE)
    with pytest.raises(DialogueLimited) as error:
        restarted.reserve('third', user_id=ALICE)
    assert error.value.code == 'user_daily_limit'


def test_storage_error_rolls_back_global_counter(budget_db):
    budget = CallBudget(budget_db)
    with pytest.raises(BudgetUnavailable):
        budget.reserve('unknown-account', user_id=str(uuid4()))  # Foreign key rejection.
    with budget_db.connect() as c:
        assert c.scalar(text('SELECT COUNT(*) FROM tutor_daily_usage')) == 0
    budget.reserve('valid', user_id=ALICE)
    with pytest.raises(BudgetUnavailable):
        budget.reserve('valid', user_id=BOB)
    with budget_db.connect() as c:
        assert c.scalar(text('SELECT calls FROM tutor_daily_usage')) == 1
        assert c.scalar(text('SELECT COUNT(*) FROM tutor_user_daily_usage')) == 1


def test_app_cannot_delete_counters_or_change_their_owner(budget_db):
    CallBudget(budget_db).reserve('first', user_id=ALICE)
    for sql in ["DELETE FROM tutor_daily_usage", "UPDATE tutor_session_usage SET user_id=:user", "UPDATE tutor_daily_usage SET day='2020-01-01'"]:
        with pytest.raises(DBAPIError), budget_db.begin() as c:
            c.execute(text(sql), {'user': BOB})


def test_missing_database_does_not_fall_back_to_sqlite(tmp_path, monkeypatch):
    unused = tmp_path / 'tutor-usage.sqlite3'
    monkeypatch.setenv('TUTOR_USAGE_DB', str(unused))
    with pytest.raises(BudgetUnavailable):
        CallBudget().reserve('first', user_id=ALICE)
    assert not unused.exists()
