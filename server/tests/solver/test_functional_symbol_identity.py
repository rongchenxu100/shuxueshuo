from types import SimpleNamespace

import sympy as sp

from shuxueshuo_server.solver.contracts import PointRef
from shuxueshuo_server.solver.runtime.functional_symbol_identity import (
    runtime_free_symbol_ids,
    runtime_free_symbols,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)


def test_runtime_symbol_uses_registered_math_object_identity() -> None:
    symbol = sp.Symbol("a")
    registry = MathObjectRegistry()
    expected = registry.register_handle("symbol:problem:a")
    assert expected is not None

    actual = runtime_free_symbol_ids(
        symbol + 1,
        context=SimpleNamespace(symbols={"a": symbol}),
        registry=registry,
    )

    assert actual == (expected,)


def test_method_created_symbol_uses_declared_return_identity() -> None:
    symbol = sp.Symbol("_axis_parameter")
    expected = MathObjectId(
        "symbol:ii:axis_parameter",
        "symbol",
        "ii",
    )

    actual = runtime_free_symbol_ids(
        symbol + 1,
        context=SimpleNamespace(symbols={}),
        registry=MathObjectRegistry(),
        declared_runtime_symbols={symbol: expected},
    )

    assert actual == (expected,)


def test_point_ref_definition_participates_in_runtime_symbol_identity() -> None:
    b = sp.Symbol("b", real=True)
    point_ref = PointRef(
        "M",
        "$question.iii.points.M",
        definition={"x": b + sp.Rational(1, 2)},
        scope_id="iii",
    )

    assert runtime_free_symbols(point_ref) == (b,)
