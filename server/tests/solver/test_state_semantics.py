from __future__ import annotations

from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
    state_kind_for_runtime_type,
)


def test_runtime_type_state_semantics_are_canonical() -> None:
    assert state_kind_for_runtime_type("MinimumExpression") == "expression"
    assert state_kind_for_runtime_type("Symbol") == "symbol"
    assert state_kind_for_runtime_type("Line") == "locus"
    assert state_kind_for_runtime_type("Point") == "coordinate"
    assert state_kind_for_runtime_type("Expression|MinimumExpression") == "expression"

    assert object_kind_for_runtime_type("Symbol") == "symbol"
    assert object_kind_for_runtime_type("ParameterValue") == "symbol"
    assert object_kind_for_runtime_type("PointRef|Point") == "point"
