from __future__ import annotations

import sympy as sp
import pytest

from shuxueshuo_server.solver.contracts import PointRef
from shuxueshuo_server.solver.runtime.symbolic_state_representation import (
    SymbolicStateRepresentationError,
    polynomial_state_relations,
    project_symbolic_input_view,
)


def test_structured_inputs_project_to_equivalent_function_basis() -> None:
    x, b, c = sp.symbols("x b c", real=True)
    source = x**2 - b * x + c
    runtime = x**2 + (c + 1) * x + c
    point = PointRef(
        "M",
        "$question.iii.points.M",
        definition={"x": b + sp.Rational(1, 2)},
        scope_id="iii",
    )
    value = {
        "point": point,
        "candidate_points": [(b, 0)],
        "constraint": {"operator": ">", "value": b},
    }

    view = project_symbolic_input_view(
        value,
        allowed_symbols=(c,),
        representable_symbols=(b, c),
        relations=polynomial_state_relations(
            source,
            runtime,
            independent_symbol=x,
        ),
        excluded_symbols=(x,),
    )

    assert view.value["point"].definition["x"] == -c - sp.Rational(1, 2)
    assert view.value["candidate_points"] == [(-c - 1, 0)]
    assert view.value["constraint"]["value"] == -c - 1
    assert point.definition["x"] == b + sp.Rational(1, 2)
    assert view.proofs


def test_ambiguous_symbolic_basis_projection_fails_loud() -> None:
    x, b, c = sp.symbols("x b c", real=True)
    relations = polynomial_state_relations(
        x**2 + b**2,
        x**2 + c**2,
        independent_symbol=x,
    )

    with pytest.raises(
        SymbolicStateRepresentationError,
        match="state_representation_ambiguous",
    ):
        project_symbolic_input_view(
            b + 1,
            allowed_symbols=(c,),
            representable_symbols=(b, c),
            relations=relations,
            excluded_symbols=(x,),
        )


def test_input_already_in_allowed_basis_is_unchanged() -> None:
    x, b, c = sp.symbols("x b c", real=True)
    value = c + 2

    view = project_symbolic_input_view(
        value,
        allowed_symbols=(c,),
        representable_symbols=(b, c),
        relations=(sp.Eq(b, -c - 1),),
        excluded_symbols=(x,),
    )

    assert view.value == value
    assert view.proofs == ()
