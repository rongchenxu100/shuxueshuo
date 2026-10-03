"""SMS adapters. Never return codes to HTTP clients or log signed requests."""

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx


class SmsUnavailable(Exception):
    pass


class MockSms:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None
        self.messages = {}  # Only injected test fixtures can inspect this; no HTTP route.
        # File-backed mock = local dev site (loopback-only): fixed code, no send limits.
        # In-memory test fixtures keep random codes so OTP and rate-limit tests stay real.
        self.dev_code = "000000" if self.directory else None

    def send(self, phone, code, challenge_id):
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
                raise SmsUnavailable()
            path = self.directory / f"{challenge_id}.json"
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
            ) as stream:
                json.dump({"phone": phone, "code": code}, stream)
        else:
            self.messages[str(challenge_id)] = (phone, code)


class AliyunSms:
    """Domestic SendSms RPC over HTTPS, without implicit paid retries."""

    def __init__(self, config):
        self.config = config

    def send(self, phone, code, challenge_id):
        c = self.config
        parameters = {
            "Action": "SendSms",
            "Version": "2017-05-25",
            "Format": "JSON",
            "AccessKeyId": c.access_key,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid4()),
            "Timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RegionId": "cn-hangzhou",
            "PhoneNumbers": phone,
            "SignName": c.sign_name,
            "TemplateCode": c.template_code,
            "TemplateParam": json.dumps({"code": code}, separators=(",", ":")),
            "OutId": str(challenge_id),
        }
        encode = lambda value: quote(str(value), safe="~")
        canonical = "&".join(
            f"{encode(k)}={encode(v)}" for k, v in sorted(parameters.items())
        )
        to_sign = "POST&%2F&" + encode(canonical)
        parameters["Signature"] = base64.b64encode(
            hmac.new(
                (c.access_secret + "&").encode(),
                to_sign.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()
        try:
            # Form body keeps phone/code/signature out of URL access logs.
            response = httpx.post(
                "https://dysmsapi.aliyuncs.com/", data=parameters, timeout=15
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get("Code") != "OK":
                raise SmsUnavailable()
        except (httpx.HTTPError, ValueError):
            raise SmsUnavailable() from None
