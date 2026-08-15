from __future__ import annotations

import json

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_content import (
    decode_single_json_object,
)


def test_one_redundant_trailing_closer_is_removed() -> None:
    payload, normalizations = decode_single_json_object('{"ok":true}}')

    assert payload == {"ok": True}
    assert [item.code for item in normalizations] == [
        "functional.trailing_json_delimiter_removed"
    ]


@pytest.mark.parametrize(
    "raw",
    (
        '{"ok":true}}}',
        '{"ok":true}{"second":true}',
        '{"ok":true} explanation',
        '{"ok":',
    ),
)
def test_other_json_damage_remains_invalid(raw: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        decode_single_json_object(raw)

