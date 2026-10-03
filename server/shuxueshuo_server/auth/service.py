"""PostgreSQL-backed OTP and session lifecycle with atomic limits/consumption."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from ..product import models as m
from ..product.db import lock, transaction
from .sms import SmsUnavailable


class AuthError(Exception):
    def __init__(self, code, message, status=400, retry_after=0):
        self.code, self.message, self.status, self.retry_after = (
            code,
            message,
            status,
            retry_after,
        )
        super().__init__(message)


class AuthService:
    def __init__(self, db, config, sms, clock=None):
        self.db, self.config, self.sms = db, config, sms
        self.clock = clock or (lambda: datetime.now(UTC))

    def digest(self, purpose, value):
        return hmac.new(
            self.config.secret.encode(), f"{purpose}:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def rate(self, c, name, value, maximum, seconds, now):
        key = self.digest("rate", f"{name}:{value}")
        lock(c, "student.auth.rate", key)
        table = m.student_auth_limits
        row = c.execute(select(table).where(table.c.key == key)).mappings().first()
        if row and row["expires_at"] > now and row["count"] >= maximum:
            raise AuthError(
                "rate_limited",
                "操作太频繁，请稍后再试。",
                429,
                max(1, int((row["expires_at"] - now).total_seconds())),
            )
        values = {
            "key": key,
            "count": row["count"] + 1 if row and row["expires_at"] > now else 1,
            "expires_at": row["expires_at"]
            if row and row["expires_at"] > now
            else now + timedelta(seconds=seconds),
        }
        c.execute(
            insert(table)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={k: v for k, v in values.items() if k != "key"},
            )
        )

    def send(self, phone, ip):
        now, challenge_id = self.clock(), uuid4()
        code = f"{secrets.randbelow(1000000):06d}"
        t = m.student_sms_challenges
        # Commit reservations before the network call; failures still consume budget.
        with transaction(self.db) as c:
            self.rate(c, "sms-global", "all", self.config.daily_limit, 86400, now)
            self.rate(c, "sms-ip", ip, 20, 3600, now)
            self.rate(c, "sms-phone", phone, 10, 86400, now)
            self.rate(c, "sms-cooldown", phone, 1, self.config.cooldown_seconds, now)
            c.execute(
                t.insert().values(
                    id=challenge_id,
                    phone=phone,
                    code_hash=self.digest("otp", f"{challenge_id}:{phone}:{code}"),
                    created_at=now,
                    expires_at=now + timedelta(seconds=self.config.code_seconds),
                    status="pending",
                )
            )
        try:
            self.sms.send(phone, code, challenge_id)
        except (SmsUnavailable, OSError):
            with transaction(self.db) as c:
                c.execute(
                    t.update().where(t.c.id == challenge_id).values(status="failed")
                )
            raise AuthError(
                "sms_unavailable", "短信暂时发送失败，请稍后重试。", 503
            ) from None
        with transaction(self.db) as c:
            c.execute(t.update().where(t.c.id == challenge_id).values(status="sent"))
        return {
            "challenge_id": str(challenge_id),
            "retry_after": self.config.cooldown_seconds,
            "expires_in": self.config.code_seconds,
        }

    def verify(self, phone, challenge_id, code, ip, old_token=None):
        now = self.clock()
        # Separate transaction: failed verification must not roll back IP limits.
        with transaction(self.db) as c:
            self.rate(c, "verify-ip", ip, 30, 900, now)
        t = m.student_sms_challenges
        result = None
        with transaction(self.db) as c:
            row = (
                c.execute(select(t).where(t.c.id == challenge_id).with_for_update())
                .mappings()
                .first()
            )
            if (
                row
                and row["status"] == "sent"
                and row["consumed_at"] is None
                and row["expires_at"] > now
                and row["attempts"] < 5
            ):
                c.execute(
                    t.update()
                    .where(t.c.id == challenge_id)
                    .values(attempts=row["attempts"] + 1)
                )
                if row["phone"] == phone and hmac.compare_digest(
                    row["code_hash"],
                    self.digest("otp", f"{challenge_id}:{phone}:{code}"),
                ):
                    user_id = c.scalar(
                        text("SELECT register_student_phone(:phone, :id)"),
                        {"phone": phone, "id": uuid4()},
                    )
                    c.execute(
                        t.update().where(t.c.id == challenge_id).values(consumed_at=now)
                    )
                    token = secrets.token_urlsafe(32)
                    c.execute(
                        m.student_login_sessions.insert().values(
                            token_hash=self.digest("session", token),
                            user_id=user_id,
                            created_at=now,
                            expires_at=now
                            + timedelta(seconds=self.config.session_seconds),
                        )
                    )
                    if old_token:
                        self._revoke(c, old_token, now)
                    result = (
                        {"id": str(user_id), "phone": phone[:3] + "****" + phone[-4:]},
                        token,
                    )
        if result is None:
            raise AuthError("invalid_code", "验证码无效或已过期，请重新获取。")
        return result

    def current_user(self, token):
        if not token or len(token) > 128:
            return None
        sessions, phones = m.student_login_sessions, m.student_phone_identities
        with transaction(self.db) as c:
            row = (
                c.execute(
                    select(sessions.c.user_id, phones.c.phone)
                    .join(phones, phones.c.user_id == sessions.c.user_id)
                    .where(
                        sessions.c.token_hash == self.digest("session", token),
                        sessions.c.revoked_at.is_(None),
                        sessions.c.expires_at > self.clock(),
                    )
                )
                .mappings()
                .first()
            )
        if row:
            return {
                "id": str(row["user_id"]),
                "phone": row["phone"][:3] + "****" + row["phone"][-4:],
            }
        return None

    def _revoke(self, c, token, now):
        t = m.student_login_sessions
        c.execute(
            t.update()
            .where(
                t.c.token_hash == self.digest("session", token),
                t.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    def logout(self, token):
        if token and len(token) <= 128:
            with transaction(self.db) as c:
                self._revoke(c, token, self.clock())
