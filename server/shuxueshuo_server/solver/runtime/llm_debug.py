"""Provider-neutral helpers for stable, redacted LLM debug artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


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
    text = json.dumps(safe_debug_json(payload), ensure_ascii=False, indent=2, default=str)
    # A completed JSON file is the journal's publication boundary.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = output.name
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


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
