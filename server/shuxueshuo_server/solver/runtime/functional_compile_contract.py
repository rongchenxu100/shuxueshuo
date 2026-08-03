"""Typed compile accessors with a Track D legacy-call compatibility edge."""

from __future__ import annotations

from typing import Any


def compile_capability_id(call: Any) -> str:
    return getattr(call, "capability_id", getattr(call, "recipe_hint", ""))


def compile_target_handle(call: Any) -> str:
    return getattr(call, "target_handle", getattr(call, "target", ""))


def compile_input_handles(call: Any) -> tuple[str, ...]:
    return tuple(
        getattr(call, "input_handles", getattr(call, "reads", ()))
    )


def compile_created_entities(call: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(call, "created_entities", getattr(call, "creates", ()))
    )


def compile_return_outputs(call: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(call, "return_outputs", getattr(call, "produces", ()))
    )


__all__ = [
    "compile_capability_id",
    "compile_created_entities",
    "compile_input_handles",
    "compile_return_outputs",
    "compile_target_handle",
]
