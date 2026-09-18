"""Deprecated local reloader entry point.

Local development deliberately keeps running services alive across code edits.
Restart them explicitly through the admin CLI when a process restart is needed.
"""
from __future__ import annotations

import os
from pathlib import Path


def _interesting(path: str) -> bool:
    parts = Path(path).parts
    if '__pycache__' in parts or '.venv' in parts or 'node_modules' in parts:
        return False
    suffix = Path(path).suffix
    return suffix in {'', '.py', '.toml', '.lock', '.json', '.jinja', '.j2', '.md', '.mjs', '.js', '.css'}


def main() -> int:
    print('reloader.disabled; restart local services manually', flush=True)
    return 0


if __name__ == '__main__':
    # Ensure children inherit the same instance env the admin starter set.
    os.environ.setdefault('PRODUCT_MODE', 'local')
    raise SystemExit(main())
