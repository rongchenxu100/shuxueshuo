"""Small-pilot call budgets. Reserve before contacting the provider, never refund.

The site PostgreSQL pool stores only counters and internal user/session IDs,
never conversations or credentials. Reserve all counters atomically before a call.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import CancelScope
from dotenv import dotenv_values
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from ..product import models as m
from ..product.db import transaction


class DialogueLimited(Exception):
    def __init__(self, code, message, retry_after=None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class BudgetUnavailable(Exception):
    pass


class CallBudget:
    def __init__(self, db=None, session_limit=None, daily_limit=None,
                 failure_cooldown=None, clock=time.time, *, user_daily_limit=None):
        config = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env"), **os.environ}

        def setting(name, default):
            value = config.get(name)
            return default if value is None or not str(value).strip() else value

        self.db = db
        self.session_limit = int(session_limit if session_limit is not None else setting("TUTOR_SESSION_CALL_LIMIT", 50))
        self.daily_limit = int(daily_limit if daily_limit is not None else setting("TUTOR_DAILY_CALL_LIMIT", 200))
        self.user_daily_limit = int(user_daily_limit if user_daily_limit is not None else setting("TUTOR_USER_DAILY_CALL_LIMIT", 50))
        self.failure_cooldown = float(failure_cooldown if failure_cooldown is not None else setting("TUTOR_FAILURE_COOLDOWN_SECONDS", 5))
        if min(self.session_limit, self.daily_limit, self.user_daily_limit, self.failure_cooldown) < 0:
            raise ValueError("Tutor limits must be nonnegative")
        self.clock = clock

    def reserve(self, session_id, *, user_id):
        if self.db is None or self.db.dialect.name != "postgresql":
            raise BudgetUnavailable()
        try:
            owner = UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            raise BudgetUnavailable() from None
        now = self.clock()
        local = datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai"))
        day = local.date()
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int(midnight.timestamp() - now) + 1)
        daily, personal, session = m.tutor_daily_usage, m.tutor_user_daily_usage, m.tutor_session_usage
        try:
            with transaction(self.db) as c:
                # Always lock global day -> account/day -> session. Inserts participate
                # in the same transaction, including first-use races. Never hold a lock
                # while calling the model. Rejections roll back all three counters.
                c.execute(insert(daily).values(day=day).on_conflict_do_nothing())
                total = c.execute(select(daily.c.calls).where(daily.c.day == day).with_for_update()).scalar_one()
                c.execute(insert(personal).values(user_id=owner, day=day).on_conflict_do_nothing())
                user_key = (personal.c.user_id == owner) & (personal.c.day == day)
                used = c.execute(select(personal.c.calls).where(user_key).with_for_update()).scalar_one()
                c.execute(insert(session).values(session_id=session_id, user_id=owner).on_conflict_do_nothing())
                session_key = session.c.session_id == session_id
                row = c.execute(select(session).where(session_key).with_for_update()).mappings().one()
                if row['user_id'] != owner:
                    raise BudgetUnavailable()
                if row['calls'] >= self.session_limit:
                    raise DialogueLimited("session_limit", "本次老师交流次数已用完，可以继续点选练习。")
                if used >= self.user_daily_limit:
                    raise DialogueLimited("user_daily_limit", "你今天的 AI 提问与提示次数已用完，明天零点恢复；现在仍可点选练习。", retry_after)
                if total >= self.daily_limit:
                    raise DialogueLimited("daily_limit", "全站今天的 AI 服务额度已用完，明天零点恢复；现在仍可点选练习。", retry_after)
                if row['retry_at'] > now:
                    raise DialogueLimited("retry_cooldown", "老师暂时未能回复，请稍后再试。", max(1, int(row['retry_at'] - now) + 1))
                c.execute(update(session).where(session_key).values(calls=session.c.calls + 1))
                c.execute(update(personal).where(user_key).values(calls=personal.c.calls + 1))
                c.execute(update(daily).where(daily.c.day == day).values(calls=daily.c.calls + 1))
        except (SQLAlchemyError, OSError) as exc:
            raise BudgetUnavailable() from exc
        return self.user_daily_limit - used - 1

    def failed(self, session_id):
        if self.db is None:
            raise BudgetUnavailable()
        try:
            with transaction(self.db) as c:
                c.execute(update(m.tutor_session_usage).where(
                    m.tutor_session_usage.c.session_id == session_id
                ).values(retry_at=self.clock() + self.failure_cooldown))
        except (SQLAlchemyError, OSError) as exc:
            raise BudgetUnavailable() from exc


class BudgetedTutor:
    def __init__(self, tutor, budget, session_id, *, user_id):
        self.tutor, self.budget, self.session_id = tutor, budget, session_id
        self.user_id = user_id
        self.remaining = None

    async def respond(self, **data):
        self.remaining = await run_in_threadpool(self.budget.reserve, self.session_id, user_id=self.user_id)
        try:
            return await self.tutor.respond(**data)
        except BaseException:
            # A timeout/cancelled request may already have been billed.
            with CancelScope(shield=True):
                await run_in_threadpool(self.budget.failed, self.session_id)
            raise
