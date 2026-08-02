"""Shared classification for non-retryable planner configuration failures."""

from __future__ import annotations


def is_planner_configuration_failure_code(code: str | None) -> bool:
    """Return whether a structured code represents planner-owned drift.

    Functional typed-authority failures use specific ``planner.*`` codes while
    legacy configuration failures retain ``planner_configuration_error``.
    Both forms must block compatibility gates and mathematical retries.
    """

    return code == "planner_configuration_error" or bool(
        code and code.startswith("planner.")
    )
