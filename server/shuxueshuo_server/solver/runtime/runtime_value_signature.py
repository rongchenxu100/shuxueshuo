"""Stable signatures for values carried by runtime authorities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.extraction.source_identity import stable_hash


def runtime_value_signature(value: Any) -> str:
    """Hash a mathematical value without depending on repr or object address."""

    return stable_hash(_canonical_runtime_value_payload(value))


def _canonical_runtime_value_payload(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return {"sympy": sp.srepr(sp.simplify(value))}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_runtime_value_payload(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_runtime_value_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return _canonical_runtime_value_payload(to_payload())
    raise ValueError(
        "planner.runtime_value_signature_unsupported: "
        f"{type(value).__name__}"
    )
