"""Scoped, durable image upload reuse. File operations never perform inference."""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter


class FilesAPIError(ValueError):
    pass


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def valid_file_id(value):
    return (
        isinstance(value, str)
        and len(value) <= 128
        and bool(re.fullmatch(r"file-api-[A-Za-z0-9_-]+", value))
    )


def _field(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


class DeepSeekFileCache:
    """One upload per credential/endpoint/image, serialized across processes."""

    def __init__(
        self, directory, *, api_key, base_url, lifetime=86400, clock=time.time
    ):
        if not api_key or not base_url or not 3600 <= lifetime <= 2592000:
            raise FilesAPIError("deepseek.files_invalid_config")
        self.scope = sha256(
            (base_url.rstrip("/") + "\0" + api_key).encode()
        ).hexdigest()
        self.directory = Path(directory) / self.scope
        self.lifetime, self.clock = lifetime, clock

    def resolve(
        self,
        image,
        client,
        events,
        *,
        timeout=60,
        minimum_remaining=630,
        persist_events=lambda: None,
    ):
        digest = sha256(image.content).hexdigest()
        if digest != image.artifact.sha256:
            raise FilesAPIError("deepseek.files_image_hash_mismatch")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (digest + ".json")
        with (self.directory / (digest + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cached = self._read(path)
            if (
                cached
                and cached.get("scope") == self.scope
                and cached.get("sha256") == digest
                and cached.get("bytes") == len(image.content)
                and valid_file_id(cached.get("file_id"))
                and isinstance(cached.get("expires_at"), (int, float))
                and cached["expires_at"] > self.clock() + minimum_remaining
            ):
                events.append(
                    {
                        "operation": "cache_hit",
                        "sha256": digest,
                        "file_id": cached["file_id"],
                        "api_calls": 0,
                    }
                )
                return cached
            suffix = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }.get(image.artifact.media_type)
            if suffix is None:
                raise FilesAPIError("deepseek.files_unsupported_image")
            event = {
                "operation": "upload",
                "status": "started",
                "sha256": digest,
                "api_calls": 1,
            }
            events.append(event)
            persist_events()  # Durable before the upload; unknown outcomes remain observable.
            started = perf_counter()
            try:
                uploaded = client.files.create(
                    file=(digest + suffix, image.content, image.artifact.media_type),
                    purpose="user_data",
                    expires_after={"anchor": "created_at", "seconds": self.lifetime},
                    timeout=timeout,
                )
                file_id, expires = (
                    _field(uploaded, "id"),
                    _field(uploaded, "expires_at"),
                )
                if (
                    not valid_file_id(file_id)
                    or _field(uploaded, "bytes") != len(image.content)
                    or _field(uploaded, "purpose") != "user_data"
                    or not isinstance(expires, (int, float))
                    or not self.clock() + minimum_remaining
                    < expires
                    <= self.clock() + self.lifetime + 300
                ):
                    raise FilesAPIError("deepseek.files_invalid_upload_response")
                cached = {
                    "file_id": file_id,
                    "sha256": digest,
                    "scope": self.scope,
                    "bytes": len(image.content),
                    "expires_at": expires,
                    "uploaded_at": self.clock(),
                }
                save_json(path, cached)
                event.update(status="completed", file_id=file_id, expires_at=expires)
                return cached
            except Exception as exc:
                event.update(status="failed", error_type=type(exc).__name__)
                if isinstance(exc, FilesAPIError):
                    raise
                # SDK exception strings can contain credentials or signed URLs.
                raise FilesAPIError("deepseek.files_upload_failed") from exc
            finally:
                event["elapsed_ms"] = round((perf_counter() - started) * 1000)

    def invalidate(self, digest, file_id, events):
        path = self.directory / (digest + ".json")
        with (self.directory / (digest + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cached = self._read(path)
            if cached and cached.get("file_id") == file_id:
                save_json(path, {**cached, "expires_at": 0})
                events.append(
                    {
                        "operation": "invalidate",
                        "sha256": digest,
                        "file_id": file_id,
                        "api_calls": 0,
                    }
                )

    @staticmethod
    def _read(path):
        try:
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, ValueError):
            return None


def rejected_file_ids(exc, current_ids):
    """Only invalidate an explicitly missing/expired reference, never any 400/404."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return set()
    error = body.get("error", body)
    if not isinstance(error, dict):
        return set()
    code, message = str(error.get("code", "")), str(error.get("message", ""))
    recognized = code in {"file_not_found", "file_expired", "invalid_file_id"}
    missing = any(
        word in message.lower() for word in ("not found", "expired", "not exist")
    )
    ids = set(current_ids)
    named = {file_id for file_id in ids if file_id in message}
    if (recognized or missing) and named:
        return named
    if recognized and len(ids) == 1:
        return ids
    return set()
