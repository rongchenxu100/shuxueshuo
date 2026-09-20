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


def test_trailing_non_json_markup_is_discarded() -> None:
    raw = (
        '{"format":"functional-plan-content/v2","goal_plans":{}}'
        "</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>"
    )

    payload, normalizations = decode_single_json_object(raw)

    assert payload == {"format": "functional-plan-content/v2", "goal_plans": {}}
    assert [item.code for item in normalizations] == [
        "functional.trailing_non_json_discarded"
    ]
    assert "DSML" in normalizations[0].message


def test_trailing_prose_after_complete_object_is_discarded() -> None:
    payload, normalizations = decode_single_json_object(
        '{"ok":true} explanation'
    )

    assert payload == {"ok": True}
    assert [item.code for item in normalizations] == [
        "functional.trailing_non_json_discarded"
    ]


@pytest.mark.parametrize(
    "raw",
    (
        '{"ok":true}}}',
        '{"ok":true}{"second":true}',
        '{"ok":true}[1]',
        '{"ok":true},{"second":true}',
        '{"ok":true} true',
        '{"ok":true}}</markup>',
        '{"ok":',
    ),
)
def test_other_json_damage_remains_invalid(raw: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        decode_single_json_object(raw)
