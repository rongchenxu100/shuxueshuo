"""Explicit opt-in configuration; no credentials or test mode defaults in production."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "disabled"
    environment: str = "production"
    origin: str = "https://shuxueshuo.com"
    secret: str = field(default="", repr=False)
    secure: bool = True
    session_seconds: int = 30 * 86400
    code_seconds: int = 300
    cooldown_seconds: int = 60
    daily_limit: int = 200
    mock_directory: Path | None = None
    access_key: str = field(default="", repr=False)
    access_secret: str = field(default="", repr=False)
    sign_name: str = ""
    template_code: str = ""

    def __post_init__(self):
        if self.mode not in {"disabled", "mock", "aliyun_sms"}:
            raise ValueError("AUTH_SMS_MODE must be disabled, mock or aliyun_sms")
        if self.environment not in {"production", "development", "test"}:
            raise ValueError("Invalid AUTH_ENVIRONMENT")
        if self.mode == "disabled":
            return
        origin = urlsplit(self.origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
        ):
            raise ValueError(
                "AUTH_ORIGIN must be an exact origin without a trailing slash"
            )
        if len(self.secret) < 32:
            raise ValueError("AUTH_SECRET must contain at least 32 characters")
        if self.environment == "production" and (
            self.mode == "mock" or not self.secure or origin.scheme != "https"
        ):
            raise ValueError("Production requires real SMS and HTTPS cookies")
        if self.environment != "production" and origin.hostname not in {
            "localhost",
            "127.0.0.1",
            "testserver",
        }:
            raise ValueError("Development authentication requires a loopback origin")
        if (
            min(
                self.session_seconds,
                self.code_seconds,
                self.cooldown_seconds,
                self.daily_limit,
            )
            <= 0
        ):
            raise ValueError("Auth limits must be positive")
        if self.mode == "aliyun_sms" and not all(
            (self.access_key, self.access_secret, self.sign_name, self.template_code)
        ):
            raise ValueError("Aliyun SMS credentials, sign and template are required")

    @classmethod
    def from_env(cls):
        return cls(
            mode=os.getenv("AUTH_SMS_MODE", "disabled"),
            environment=os.getenv("AUTH_ENVIRONMENT", "production"),
            origin=os.getenv("AUTH_ORIGIN", "https://shuxueshuo.com"),
            secret=os.getenv("AUTH_SECRET", ""),
            secure=os.getenv("AUTH_COOKIE_SECURE", "1") == "1",
            session_seconds=int(os.getenv("AUTH_SESSION_SECONDS", str(30 * 86400))),
            daily_limit=int(os.getenv("AUTH_SMS_DAILY_LIMIT", "200")),
            mock_directory=Path(os.environ["AUTH_MOCK_DIRECTORY"])
            if os.getenv("AUTH_MOCK_DIRECTORY")
            else None,
            access_key=os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", ""),
            access_secret=os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", ""),
            sign_name=os.getenv("ALIYUN_SMS_SIGN_NAME", ""),
            template_code=os.getenv("ALIYUN_SMS_TEMPLATE_CODE", ""),
        )
