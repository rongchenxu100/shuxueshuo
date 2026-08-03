"""Accessors for the typed Functional capability compile request."""

from __future__ import annotations

from typing import Any


def compile_capability_id(call: Any) -> str:
    return call.capability_id


def compile_target_handle(call: Any) -> str:
    return call.target_handle


def compile_input_handles(call: Any) -> tuple[str, ...]:
    return tuple(call.input_handles)


def compile_created_entities(call: Any) -> tuple[Any, ...]:
    return tuple(call.created_entities)


def compile_return_outputs(call: Any) -> tuple[Any, ...]:
    return tuple(call.return_outputs)


__all__ = [
    "compile_capability_id",
    "compile_created_entities",
    "compile_input_handles",
    "compile_return_outputs",
    "compile_target_handle",
]
