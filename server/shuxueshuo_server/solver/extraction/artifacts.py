"""Content-addressed artifacts for problem extraction."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef


class ExtractionArtifactStore:
    """Small local artifact store used by extraction workers and review tools."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        kind: str,
        content: bytes,
        media_type: str,
        suffix: str,
    ) -> ExtractionArtifactRef:
        if not kind.strip() or not suffix.startswith("."):
            raise ValueError("artifact kind and dotted suffix are required")
        digest = sha256(content).hexdigest()
        target = self.root / digest[:2] / f"{digest}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                handle.write(content)
                temporary = Path(handle.name)
            os.replace(temporary, target)
        elif target.read_bytes() != content:
            raise RuntimeError(f"artifact digest collision at {target}")
        return ExtractionArtifactRef(
            artifact_id=f"artifact:{kind}:{digest}",
            kind=kind,
            sha256=digest,
            media_type=media_type,
            byte_size=len(content),
            locator=str(target),
        )

    def put_json(self, *, kind: str, payload: Any) -> ExtractionArtifactRef:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.put_bytes(
            kind=kind,
            content=content,
            media_type="application/json",
            suffix=".json",
        )

    def read_bytes(self, artifact: ExtractionArtifactRef) -> bytes:
        if artifact.locator is None:
            raise ValueError("artifact locator is unavailable")
        path = Path(artifact.locator).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("artifact locator escapes store root") from exc
        content = path.read_bytes()
        if sha256(content).hexdigest() != artifact.sha256:
            raise ValueError("artifact content hash mismatch")
        if artifact.byte_size is not None and len(content) != artifact.byte_size:
            raise ValueError("artifact byte size mismatch")
        return content
