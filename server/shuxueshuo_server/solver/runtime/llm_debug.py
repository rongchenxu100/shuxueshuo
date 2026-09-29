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


def _debug_json_default(value: Any) -> Any:
    """Convert only objects the native JSON encoder cannot already encode."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return str(value)


class DebugArtifactJournal:
    """Per-solve, content-versioned audit writer (not a proof trust cache).

    Latest filenames remain compatible. The index points at immutable versions,
    so a later phase cannot destroy a failed/partial attempt's evidence. Full
    diagnostic mode includes legacy views; compact audit omits those views,
    never the canonical evidence roles. Both use compact native JSON encoding;
    pretty-printing large proofs is not part of the solve path. No cache survives
    a solve.
    """

    def __init__(self, directory: Path, *, mode: str = "full_diagnostic") -> None:
        if mode not in {"compact_audit", "full_diagnostic"}:
            raise ValueError(f"unknown debug artifact mode: {mode}")
        self.directory = Path(directory)
        self.mode = mode
        self._latest: dict[str, dict[str, str]] = {}
        self._history: dict[str, list[dict[str, str]]] = {}
        self._versions: dict[str, dict[str, str]] = {}
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
        """Drop publication metadata at solve exit; keep only aggregate metrics."""
        self._latest.clear()
        self._versions.clear()
        self._history.clear()

    def write_json(self, name: str, value: Any) -> dict[str, str]:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("artifact role must be a filename")
        self.metrics["publications"] += 1
        # Encode once, with no recursive snapshot conversion/comparison and no
        # caller-owned payload retained. Content hashes select immutable files.
        self.metrics["serializations"] += 1
        try:
            text = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"),
                default=_debug_json_default,
            )
        except TypeError:
            # Native dict encoding never calls default() for unsupported keys.
            # Rare tuple/dataclass keys use the historical str(key) conversion,
            # including nested mappings; ordinary proof payloads avoid a walk.
            self.metrics["conversions"] += 1
            self.metrics["serializations"] += 1
            text = json.dumps(
                safe_debug_json(value), ensure_ascii=False, separators=(",", ":"),
                default=_debug_json_default,
            )
        return self._publish(name, text)

    def write_text(self, name: str, value: str) -> dict[str, str]:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("artifact role must be a filename")
        self.metrics["publications"] += 1
        return self._publish(name, value)

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
        version_key = f"{digest}{Path(name).suffix}"
        saved = self._versions.get(version_key)
        if saved is not None:
            if self._latest.get(name) != saved:
                self._link_latest(name, self.directory / saved["file"])
                self._latest[name] = saved
            self.metrics["unchanged"] += 1
            return dict(saved)
        versions = self.directory / ".versions"
        versions.mkdir(parents=True, exist_ok=True)
        version = versions / version_key
        # Versions may already exist after an interrupted writer/reopened journal.
        if not version.exists():
            _atomic_text(version, text)
            self.metrics["writes"] += 1
            self.metrics["bytes_written"] += len(data)
        elif version.read_bytes() != data:
            raise ValueError("artifact version content mismatch")
        version.chmod(0o444)
        self._link_latest(name, version)
        saved = {
            "status": "saved",
            "file": str(version.relative_to(self.directory)),
            "sha256": digest,
        }
        self._versions[version_key] = saved
        self._latest[name] = saved
        return dict(saved)

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
