"""微信公众平台 JS-SDK：access_token、jsapi_ticket 缓存与 signature。"""

from __future__ import annotations

import hashlib
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

_NONCE_CHARS = string.ascii_letters + string.digits


@dataclass
class _CachedItem:
    value: str
    expires_at: float  # unix timestamp


class WeChatJsSdkSigner:
    """单机内存缓存；多 worker 请改用 Redis 或 workers=1。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        allowed_origin: str,
        http_timeout: float = 10.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._allowed_origin = allowed_origin.rstrip("/")
        self._http_timeout = http_timeout
        self._token_cache: _CachedItem | None = None
        self._ticket_cache: _CachedItem | None = None

    def validate_page_url(self, url: str) -> None:
        """校验当前页 URL 与允许的站点同源，避免仅靠 startswith 被 example.com.evil 绕过。"""
        page = urlparse(url)
        if page.scheme not in ("http", "https") or not page.hostname:
            raise ValueError("invalid url")
        base = urlparse(self._allowed_origin)
        if base.scheme not in ("http", "https") or not base.hostname:
            raise ValueError("allowed origin misconfigured")

        def effective_port(scheme: str, port: int | None) -> int:
            if port is not None:
                return port
            return 443 if scheme == "https" else 80

        if page.scheme != base.scheme:
            raise ValueError("url not allowed")
        if page.hostname.lower() != base.hostname.lower():
            raise ValueError("url not allowed")
        if effective_port(page.scheme, page.port) != effective_port(base.scheme, base.port):
            raise ValueError("url not allowed")

        base_path = (base.path or "").rstrip("/")
        if not base_path:
            return
        page_path = page.path or "/"
        if page_path != base_path and not page_path.startswith(base_path + "/"):
            raise ValueError("url not allowed")

    async def build_config(self, page_url: str) -> dict[str, Any]:
        """返回 wx.config 所需字段（含 signature）。"""
        self.validate_page_url(page_url)
        normalized = self._normalize_url(page_url)
        ticket = await self._get_jsapi_ticket()
        nonce_str = "".join(secrets.choice(_NONCE_CHARS) for _ in range(16))
        timestamp = int(time.time())
        sign_src = (
            f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={timestamp}&url={normalized}"
        )
        signature = hashlib.sha1(sign_src.encode("utf-8")).hexdigest()
        return {
            "appId": self._app_id,
            "timestamp": timestamp,
            "nonceStr": nonce_str,
            "signature": signature,
        }

    @staticmethod
    def _normalize_url(url: str) -> str:
        """与微信一致：参与签名的 url 不含 # 及其后面部分。"""
        return url.split("#", 1)[0]

    async def _get_jsapi_ticket(self) -> str:
        token = await self._get_access_token()
        now = time.time()
        if self._ticket_cache and self._ticket_cache.expires_at > now + 60:
            return self._ticket_cache.value

        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            r = await client.get(
                "https://api.weixin.qq.com/cgi-bin/ticket/getticket",
                params={"access_token": token, "type": "jsapi"},
            )
            r.raise_for_status()
            data = r.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"getticket failed: {data}")
        ticket = data["ticket"]
        expires_in = int(data.get("expires_in", 7200))
        self._ticket_cache = _CachedItem(value=ticket, expires_at=now + expires_in - 120)
        return ticket

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._token_cache and self._token_cache.expires_at > now + 60:
            return self._token_cache.value

        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            r = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self._app_id,
                    "secret": self._app_secret,
                },
            )
            r.raise_for_status()
            data = r.json()
        if data.get("errcode"):
            raise RuntimeError(f"access_token failed: {data}")
        if "access_token" not in data:
            raise RuntimeError(f"access_token failed: {data}")
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        self._token_cache = _CachedItem(value=token, expires_at=now + expires_in - 120)
        return token
