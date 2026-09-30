"""Small-pilot call budgets. Reserve before contacting the provider, never refund.

SQLite is shared by all routers/processes using the same persistent path. It stores
only counters and opaque session IDs, never conversations or credentials.
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values


class DialogueLimited(Exception):
    def __init__(self, code, message, retry_after=None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class BudgetUnavailable(Exception):
    pass


class CallBudget:
    def __init__(self, path=None, session_limit=None, daily_limit=None,
                 failure_cooldown=None, clock=time.time):
        config = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env"), **os.environ}

        def setting(name, default):
            value = config.get(name)
            return default if value is None or not str(value).strip() else value

        self.path = Path(path or config.get("TUTOR_USAGE_DB") or
                         Path(__file__).resolve().parents[2] / "var/tutor-usage.sqlite3")
        self.session_limit = int(session_limit if session_limit is not None else setting("TUTOR_SESSION_CALL_LIMIT", 20))
        self.daily_limit = int(daily_limit if daily_limit is not None else setting("TUTOR_DAILY_CALL_LIMIT", 200))
        self.failure_cooldown = float(failure_cooldown if failure_cooldown is not None else setting("TUTOR_FAILURE_COOLDOWN_SECONDS", 5))
        if min(self.session_limit, self.daily_limit, self.failure_cooldown) < 0:
            raise ValueError("Tutor limits must be nonnegative")
        self.clock = clock

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, calls INTEGER NOT NULL, retry_at REAL NOT NULL DEFAULT 0)")
        return db

    def reserve(self, session_id):
        now = self.clock()
        local = datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai"))
        day = local.date().isoformat()
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        db = None
        try:
            db = self.connect()
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT calls, retry_at FROM sessions WHERE id=?", (session_id,)).fetchone()
            calls, retry_at = row or (0, 0)
            if calls >= self.session_limit:
                raise DialogueLimited("session_limit", "本次老师交流次数已用完，可以继续点选练习。")
            daily = db.execute("SELECT calls FROM daily WHERE day=?", (day,)).fetchone()
            if (daily[0] if daily else 0) >= self.daily_limit:
                raise DialogueLimited("daily_limit", "今天的老师交流额度已用完，明天可以继续；现在仍可点选练习。", max(1, int(midnight.timestamp() - now) + 1))
            if retry_at > now:
                raise DialogueLimited("retry_cooldown", "老师暂时未能回复，请稍后再试。", max(1, int(retry_at - now) + 1))
            db.execute("INSERT INTO sessions(id,calls) VALUES (?,1) ON CONFLICT(id) DO UPDATE SET calls=calls+1", (session_id,))
            db.execute("INSERT INTO daily(day,calls) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1", (day,))
            db.commit()
        except (sqlite3.Error, OSError) as exc:
            raise BudgetUnavailable() from exc
        finally:
            if db is not None:
                db.close()

    def failed(self, session_id):
        db = None
        try:
            db = self.connect()
            db.execute("UPDATE sessions SET retry_at=? WHERE id=?", (self.clock() + self.failure_cooldown, session_id))
            db.commit()
        except (sqlite3.Error, OSError) as exc:
            raise BudgetUnavailable() from exc
        finally:
            if db is not None:
                db.close()


class BudgetedTutor:
    def __init__(self, tutor, budget, session_id):
        self.tutor, self.budget, self.session_id = tutor, budget, session_id

    async def respond(self, **data):
        self.budget.reserve(self.session_id)
        try:
            return await self.tutor.respond(**data)
        except BaseException:
            # A timeout/cancelled request may already have been billed.
            self.budget.failed(self.session_id)
            raise
