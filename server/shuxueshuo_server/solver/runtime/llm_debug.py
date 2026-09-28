"""Provider-neutral helpers for stable, redacted LLM debug artifacts."""

from __future__ import annotations

import errno
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any


def safe_debug_json(value: Any) -> Any:
    # asdict() deep-copies leaves and cannot copy frozen MappingProxyType
    # authority/validation payloads. Walk fields without mutating the source.
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: safe_debug_json(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): safe_debug_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_debug_json(item) for item in value]
    return value


def write_debug_json(path: Path, payload: Any) -> None:
    text = json.dumps(
        safe_debug_json(payload), ensure_ascii=False, indent=2, default=str
    )
    _atomic_text(path, text)


def write_common_llm_attempt(
    directory: Path,
    *,
    prefix: str,
    system_prompt: str,
    user_prompt: str,
    prompt_payload: Mapping[str, Any],
    raw_response: str,
    metadata: Mapping[str, Any],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_debug_json(
        directory / f"{prefix}.prompt.json",
        prompt_payload,
    )
    (directory / f"{prefix}.prompt.system.md").write_text(
        system_prompt,
        encoding="utf-8",
    )
    (directory / f"{prefix}.prompt.user.md").write_text(
        user_prompt,
        encoding="utf-8",
    )
    (directory / f"{prefix}.raw-response.txt").write_text(
        raw_response,
        encoding="utf-8",
    )
    write_debug_json(directory / f"{prefix}.llm-metadata.json", metadata)


def contains_secret_or_data_url(value: Any) -> bool:
    """Conservative guard used by debug writers and their tests."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {"api_key", "authorization"}:
                return True
            if contains_secret_or_data_url(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(contains_secret_or_data_url(item) for item in value)
    return isinstance(value, str) and (
        "data:image/" in value or "bearer " in value.lower()
    )


_MISSING = object()


def _matches_snapshot(value: Any, snapshot: Any) -> bool:
    """Value comparison without conversion; mutable descendants are checked."""
    if is_dataclass(value) and not isinstance(value, type):
        members = fields(value)
        return (
            type(snapshot) is dict
            and tuple(snapshot) == tuple(f.name for f in members)
            and all(
                _matches_snapshot(getattr(value, f.name), snapshot[f.name])
                for f in members
            )
        )
    if isinstance(value, Mapping):
        return (
            type(snapshot) is dict
            and tuple(snapshot) == tuple(str(k) for k in value)
            and all(_matches_snapshot(v, snapshot[str(k)]) for k, v in value.items())
        )
    if isinstance(value, (list, tuple)):
        return (
            type(snapshot) is list
            and len(value) == len(snapshot)
            and all(_matches_snapshot(a, b) for a, b in zip(value, snapshot))
        )
    value = _json_leaf(value)
    if type(value) is float and type(snapshot) is float:
        return value.hex() == snapshot.hex()
    return type(value) is type(snapshot) and value == snapshot


def _json_snapshot(value: Any) -> Any:
    # Complete private JSON snapshot, including opaque leaves that json.dumps
    # historically rendered using default=str. No caller-owned containers.
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_snapshot(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _json_snapshot(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_snapshot(v) for v in value]
    return _json_leaf(value)


def _json_leaf(value: Any) -> Any:
    # Match json.dumps(default=str), including str/int Enum subclasses.
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return str(value)


class DebugArtifactJournal:
    """Per-solve, content-versioned audit writer (not a proof trust cache).

    Latest filenames remain compatible. The index points at immutable versions,
    so a later phase cannot destroy a failed/partial attempt's evidence. Full
    diagnostic mode includes legacy views; compact audit omits those views and
    whitespace, never the canonical evidence roles. No cache survives a solve.
    """

    def __init__(self, directory: Path, *, mode: str = "full_diagnostic") -> None:
        if mode not in {"compact_audit", "full_diagnostic"}:
            raise ValueError(f"unknown debug artifact mode: {mode}")
        self.directory = Path(directory)
        self.mode = mode
        self._latest: dict[str, tuple[Any, dict[str, str]]] = {}
        self._history: dict[str, list[dict[str, str]]] = {}
        self._versions: dict[str, list[tuple[Any, dict[str, str]]]] = {}
        self.metrics = {
            "publications": 0,
            "unchanged": 0,
            "serializations": 0,
            "conversions": 0,
            "writes": 0,
            "bytes_written": 0,
            "aliases": 0,
        }

    def release_snapshots(self) -> None:
        """Drop comparison payloads at solve exit; keep only aggregate metrics."""
        self._latest.clear()
        self._versions.clear()
        self._history.clear()

    def write_json(self, name: str, value: Any) -> dict[str, str]:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("artifact role must be a filename")
        self.metrics["publications"] += 1
        prior, saved = self._latest.get(name, (_MISSING, None))
        if prior is not _MISSING and _matches_snapshot(value, prior):
            self.metrics["unchanged"] += 1
            return dict(saved)
        for snapshot, saved in self._versions.get(name, ()):
            if _matches_snapshot(value, snapshot):
                self._link_latest(name, self.directory / saved["file"])
                self._latest[name] = (snapshot, saved)
                self.metrics["unchanged"] += 1
                return dict(saved)
        snapshot = _json_snapshot(value)
        self.metrics["conversions"] += 1
        text = json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2 if self.mode == "full_diagnostic" else None,
            separators=None if self.mode == "full_diagnostic" else (",", ":"),
        )
        self.metrics["serializations"] += 1
        saved = self._publish(name, text)
        self._latest[name] = (snapshot, saved)
        self._versions.setdefault(name, []).append((snapshot, saved))
        return dict(saved)

    def write_text(self, name: str, value: str) -> dict[str, str]:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("artifact role must be a filename")
        self.metrics["publications"] += 1
        prior, saved = self._latest.get(name, (_MISSING, None))
        if type(prior) is str and prior == value:
            self.metrics["unchanged"] += 1
            return dict(saved)
        saved = self._publish(name, value)
        self._latest[name] = (value, saved)
        return dict(saved)

    def write_index(self, prefix: str, value: Any) -> None:
        saved = self.write_json(f"{prefix}.evidence-index.json", value)
        if prefix not in self._history:
            path = self.directory / f"{prefix}.evidence-history.json"
            self._history[prefix] = (
                json.loads(path.read_text())["versions"] if path.exists() else []
            )
        history = self._history[prefix]
        if not history or history[-1]["sha256"] != saved["sha256"]:
            history.append({"phase": value["phase"], **saved})
        self.write_json(
            f"{prefix}.evidence-history.json",
            {
                "schema_version": "functional-attempt-history/v1",
                "semantic_attempt": value["semantic_attempt"],
                "versions": history,
            },
        )

    def _publish(self, name: str, text: str) -> dict[str, str]:
        from hashlib import sha256

        data = text.encode("utf-8")
        digest = sha256(data).hexdigest()
        versions = self.directory / ".versions"
        versions.mkdir(parents=True, exist_ok=True)
        version = versions / f"{digest}{Path(name).suffix}"
        # Versions may already exist after an interrupted writer/reopened journal.
        if not version.exists():
            _atomic_text(version, text)
            self.metrics["writes"] += 1
            self.metrics["bytes_written"] += len(data)
        elif version.read_bytes() != data:
            raise ValueError("artifact version content mismatch")
        version.chmod(0o444)
        self._link_latest(name, version)
        return {
            "status": "saved",
            "file": str(version.relative_to(self.directory)),
            "sha256": digest,
        }

    def _link_latest(self, name: str, version: Path) -> None:
        # Atomic link publishes the compatibility filename without a second
        # serialization or physical write of the full artifact.
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(
                dir=self.directory, prefix=".artifact-", suffix=".tmp"
            )
            os.close(fd)
            os.unlink(temporary)
            try:
                os.link(version, temporary)
            except OSError as exc:
                if exc.errno not in {errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM}:
                    raise
                shutil.copyfile(version, temporary)
                self.metrics["writes"] += 1
                self.metrics["bytes_written"] += version.stat().st_size
                os.chmod(temporary, 0o444)
            os.replace(temporary, self.directory / name)
            self.metrics["aliases"] += 1
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)


def _atomic_text(path: Path, text: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
